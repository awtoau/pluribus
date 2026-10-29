// Applies reference/ghidra/*.tsv to currentProgram (idempotent). arg0 = tsv dir, arg1 = report file.
// Addresses in TSVs are ELF vaddrs (nm / readelf form); image base is added here. A non-hex key is a symbol name (exact or mangled).
import ghidra.app.script.GhidraScript;
import ghidra.app.cmd.function.ApplyFunctionSignatureCmd;
import ghidra.app.util.parser.FunctionSignatureParser;
import ghidra.program.model.address.*;
import ghidra.program.model.data.*;
import ghidra.program.model.listing.*;
import ghidra.program.model.symbol.*;
import ghidra.util.data.DataTypeParser;
import java.io.*; import java.nio.file.*; import java.util.*;

public class ApplyNames extends GhidraScript {
  static final String CAT = "/pluribus";
  PrintWriter rep; String lib; int ok = 0, skip = 0, fail = 0;

  List<String[]> rows(String dir, String file, int ncol) throws Exception {
    List<String[]> out = new ArrayList<>(); Path p = Paths.get(dir, file);
    if (!Files.exists(p)) return out;
    for (String s : Files.readAllLines(p)) {
      if (s.isBlank() || s.startsWith("#")) continue;
      String[] c = s.split("\t", -1);
      if (c.length < ncol) { c = Arrays.copyOf(c, ncol); for (int i = 0; i < ncol; i++) if (c[i] == null) c[i] = ""; }
      if (c[0].equals(lib)) out.add(c);
    }
    return out;
  }
  Address addr(String key) {
    if (key.matches("(0x)?[0-9a-fA-F]+")) {
      long v = Long.parseUnsignedLong(key.replaceFirst("^0x", ""), 16);
      return currentProgram.getImageBase().add(v);
    }
    for (Symbol s : currentProgram.getSymbolTable().getSymbols(key)) return s.getAddress();
    return null;
  }
  void log(String kind, String key, String msg) { rep.println(lib + "\t" + kind + "\t" + key + "\t" + msg); }
  DataType type(String t) throws Exception {
    DataTypeManager dtm = currentProgram.getDataTypeManager();
    DataTypeParser p = new DataTypeParser(dtm, dtm, null, DataTypeParser.AllowedDataTypes.ALL);
    return p.parse(t);
  }

  public void run() throws Exception {
    String[] a = getScriptArgs();
    lib = currentProgram.getName().replaceAll("\\.so$", "");
    rep = new PrintWriter(new FileWriter(a[1], true));
    DataTypeManager dtm = currentProgram.getDataTypeManager();
    // structs first so signatures / globals can use them
    Map<String, List<String[]>> st = new LinkedHashMap<>();
    for (String[] r : rows(a[0], "structs.tsv", 8)) st.computeIfAbsent(r[1], k -> new ArrayList<>()).add(r);
    for (var e : st.entrySet()) {
      try {
        int size = Integer.parseInt(e.getValue().get(0)[2]);
        StructureDataType s = new StructureDataType(new CategoryPath(CAT), e.getKey(), size, dtm);
        for (String[] r : e.getValue()) {
          if (r[3].isEmpty()) continue;
          int off = Integer.decode(r[3]); DataType ft = type(r[5]);
          int len = ft.getLength() > 0 ? ft.getLength() : 1;
          if (off + len > size) { log("struct", e.getKey() + "+" + r[3], "field exceeds size"); fail++; continue; }
          s.replaceAtOffset(off, ft, len, r[4], r[6]);
        }
        if (!r0(e.getValue()).isEmpty()) s.setDescription(r0(e.getValue()));
        int tx = currentProgram.startTransaction("struct");
        dtm.addDataType(s, DataTypeConflictHandler.REPLACE_HANDLER);
        currentProgram.endTransaction(tx, true); ok++;
      } catch (Exception ex) { log("struct", e.getKey(), "FAIL " + ex); fail++; }
    }
    // functions: lib addr name signature source comment
    for (String[] r : rows(a[0], "functions.tsv", 6)) {
      int tx = currentProgram.startTransaction("fn");
      try {
        Address ad = addr(r[1]);
        if (ad == null) { log("func", r[1], "NOT FOUND"); fail++; continue; }
        Function f = currentProgram.getFunctionManager().getFunctionAt(ad);
        if (f == null) { f = createFunction(ad, r[2].isEmpty() ? null : r[2]); }
        if (f == null) { log("func", r[1], "no function"); fail++; continue; }
        String want = r[2];
        if (!want.isEmpty() && !want.equals(f.getName(true)) && !want.equals(f.getName())) {
          f.setName(want.contains("::") ? want.substring(want.lastIndexOf("::") + 2) : want, SourceType.USER_DEFINED);
        }
        if (!r[3].isEmpty()) {
          try {
            FunctionSignatureParser fp = new FunctionSignatureParser(currentProgram.getDataTypeManager(), null);
            FunctionDefinitionDataType fd = fp.parse(f.getSignature(), r[3]);
            new ApplyFunctionSignatureCmd(ad, fd, SourceType.USER_DEFINED, false, true).applyTo(currentProgram);
          } catch (Exception ex) { log("sig", r[1], "FAIL " + ex.getMessage()); }
        }
        if (!r[5].isEmpty()) setPlateComment(ad, r[5]);
        ok++;
      } catch (Exception ex) { log("func", r[1], "FAIL " + ex); fail++; }
      finally { currentProgram.endTransaction(tx, true); }
    }
    // globals: lib addr name type size source comment
    for (String[] r : rows(a[0], "globals.tsv", 7)) {
      int tx = currentProgram.startTransaction("glob");
      try {
        Address ad = addr(r[1]);
        if (ad == null) { log("glob", r[1], "NOT FOUND"); fail++; continue; }
        if (!r[2].isEmpty()) {
          Symbol sy = currentProgram.getSymbolTable().getPrimarySymbol(ad);
          if (sy == null || !sy.getName().equals(r[2]))
            currentProgram.getSymbolTable().createLabel(ad, r[2], SourceType.USER_DEFINED).setPrimary();
        }
        if (!r[3].isEmpty()) {
          DataType dt = type(r[3]);
          Listing l = currentProgram.getListing();
          l.clearCodeUnits(ad, ad.add(Math.max(dt.getLength(), 1) - 1), false);
          l.createData(ad, dt);
        }
        if (!r[6].isEmpty()) currentProgram.getListing().setComment(ad, CodeUnit.EOL_COMMENT, r[6]);
        ok++;
      } catch (Exception ex) { log("glob", r[1], "FAIL " + ex); fail++; }
      finally { currentProgram.endTransaction(tx, true); }
    }
    // notes: lib addr kind(plate|eol|bookmark) text source
    for (String[] r : rows(a[0], "notes.tsv", 5)) {
      int tx = currentProgram.startTransaction("note");
      try {
        Address ad = addr(r[1]);
        if (ad == null) { log("note", r[1], "NOT FOUND"); fail++; continue; }
        if (r[2].equals("plate")) setPlateComment(ad, r[3]);
        else if (r[2].equals("eol")) currentProgram.getListing().setComment(ad, CodeUnit.EOL_COMMENT, r[3]);
        else currentProgram.getBookmarkManager().setBookmark(ad, BookmarkType.NOTE, "pluribus", r[3]);
        ok++;
      } catch (Exception ex) { log("note", r[1], "FAIL " + ex); fail++; }
      finally { currentProgram.endTransaction(tx, true); }
    }
    rep.println(lib + "\tSUMMARY\tok=" + ok + " fail=" + fail); rep.close();
  }
  String r0(List<String[]> l) { return l.get(0).length > 7 ? l.get(0)[7] : ""; }
}
