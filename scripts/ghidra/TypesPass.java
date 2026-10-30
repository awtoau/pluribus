// Readability types pass (after ApplyNames + RecoverClassesFromRTTI).  arg0 = tsv dir, arg1 = report file.  Idempotent.  (#165, #168)
//  1. merge every /pluribus struct into the same-named struct in other categories (demangler stubs / RTTI class structs),
//     so existing function signatures see the fields (decompiler shows this->m_field).
//  2. per class with a vtable in vtables.tsv: struct <Class>_vtbl of named function-pointer slots; a `vptr` field at offset 0
//     of the class struct when offset 0 is free ("alias:<Other>" curated rows reuse another class's slots).
//  3. signatures.tsv: typed/named parameters for key functions.
import ghidra.app.script.GhidraScript;
import ghidra.app.cmd.function.ApplyFunctionSignatureCmd;
import ghidra.app.util.parser.FunctionSignatureParser;
import ghidra.program.model.address.*;
import ghidra.program.model.data.*;
import ghidra.program.model.listing.*;
import ghidra.program.model.symbol.*;
import java.io.*; import java.nio.file.*; import java.util.*;

public class TypesPass extends GhidraScript {
  static final String CAT = "/pluribus";
  PrintWriter rep; String lib; int merged = 0, vtbls = 0, vptrs = 0, sigs = 0, fail = 0;

  List<String[]> rows(String dir, String file, int ncol) throws Exception {
    List<String[]> out = new ArrayList<>(); Path p = Paths.get(dir, file);
    if (!Files.exists(p)) return out;
    for (String s : Files.readAllLines(p)) {
      if (s.isBlank() || s.startsWith("#")) continue;
      String[] c = s.split("\t", -1);
      if (c.length < ncol) { c = Arrays.copyOf(c, ncol); for (int i = 0; i < ncol; i++) if (c[i] == null) c[i] = ""; }
      if (c[0].equals(lib) || c[0].equals("*")) out.add(c);
    }
    return out;
  }
  void log(String kind, String key, String msg) { rep.println(lib + "\t" + kind + "\t" + key + "\t" + msg); }
  List<Structure> structsNamed(String name) {
    List<Structure> l = new ArrayList<>();
    Iterator<DataType> it = currentProgram.getDataTypeManager().getAllDataTypes();
    while (it.hasNext()) { DataType d = it.next(); if (d instanceof Structure && d.getName().equals(name)) l.add((Structure) d); }
    return l;
  }
  boolean isVptr(DataTypeComponent c) {
    String n = c.getFieldName() == null ? "" : c.getFieldName().toLowerCase();
    return n.contains("vptr") || n.contains("vftable") || n.contains("vtable");
  }

  void mergeStructs() {
    DataTypeManager dtm = currentProgram.getDataTypeManager();
    List<Structure> mine = new ArrayList<>();
    Iterator<DataType> it = dtm.getAllDataTypes();
    while (it.hasNext()) { DataType d = it.next(); if (d instanceof Structure && d.getCategoryPath().getPath().equals(CAT)) mine.add((Structure) d); }
    for (Structure m : mine) {
      for (Structure t : structsNamed(m.getName())) {
        if (t.getCategoryPath().getPath().equals(CAT)) continue;
        int tx = currentProgram.startTransaction("merge");
        try {
          if (t.getLength() < m.getLength()) t.growStructure(m.getLength() - t.getLength());
          DataTypeComponent c0 = t.getComponentAt(0);
          boolean keep0 = c0 != null && isVptr(c0);
          for (DataTypeComponent c : m.getDefinedComponents()) {
            if (keep0 && c.getOffset() < c0.getLength()) continue;
            t.replaceAtOffset(c.getOffset(), c.getDataType(), c.getLength(), c.getFieldName(), c.getComment());
          }
          merged++;
        } catch (Exception e) { log("merge", m.getName(), "FAIL " + e); fail++; }
        finally { currentProgram.endTransaction(tx, true); }
      }
    }
  }

  void vtables(String dir) throws Exception {
    DataTypeManager dtm = currentProgram.getDataTypeManager();
    Map<String, TreeMap<Integer, String>> slots = new TreeMap<>(); Map<String, String> alias = new HashMap<>();
    for (String[] r : rows(dir, "vtables.tsv", 6)) {
      if (r[3].startsWith("alias:")) { alias.put(r[1], r[3].substring(6)); continue; }
      String m = r[3]; if (m.contains("::")) m = m.substring(m.lastIndexOf("::") + 2);
      m = m.replaceAll("[^A-Za-z0-9_~]", "_").replace("~", "dtor_");
      slots.computeIfAbsent(r[1], k -> new TreeMap<>()).put(Integer.decode(r[2]), m);
    }
    for (var e : alias.entrySet()) if (slots.containsKey(e.getValue())) slots.put(e.getKey(), slots.get(e.getValue()));
    for (var e : slots.entrySet()) {
      String cls = e.getKey(); TreeMap<Integer, String> sl = e.getValue();
      if (cls.contains("<") || cls.contains(" ")) continue;
      int tx = currentProgram.startTransaction("vtbl");
      try {
        int size = sl.lastKey() + 8; StructureDataType v = new StructureDataType(new CategoryPath(CAT + "/vtbl"), cls + "_vtbl", size, dtm);
        Set<String> used = new HashSet<>();
        for (var s : sl.entrySet()) {
          String n = s.getValue(); int i = 2; String c = n; while (!used.add(c)) c = n + "_" + i++;
          v.replaceAtOffset(s.getKey(), new PointerDataType(), 8, c, "vtable slot +0x" + Integer.toHexString(s.getKey()));
        }
        DataType vt = dtm.addDataType(v, DataTypeConflictHandler.REPLACE_HANDLER); vtbls++;
        for (Structure st : structsNamed(cls)) {
          DataTypeComponent c0 = st.getComponentAt(0);
          if (st.getLength() < 8) st.growStructure(8 - st.getLength());
          if (c0 != null && (isVptr(c0) || c0.getFieldName() != null)) continue;
          st.replaceAtOffset(0, new PointerDataType(vt), 8, "vptr", "vtable pointer (vtables.tsv)"); vptrs++;
        }
      } catch (Exception ex) { log("vtbl", cls, "FAIL " + ex); fail++; }
      finally { currentProgram.endTransaction(tx, true); }
    }
  }

  void signatures(String dir) throws Exception {
    long base = currentProgram.getImageBase().getOffset();
    for (String[] r : rows(dir, "signatures.tsv", 6)) {   // lib vaddr name signature source comment
      int tx = currentProgram.startTransaction("sig");
      try {
        Address ad = currentProgram.getImageBase().add(Long.parseUnsignedLong(r[1].replaceFirst("^0x", ""), 16));
        Function f = currentProgram.getFunctionManager().getFunctionAt(ad);
        if (f == null) { log("sig", r[1], "NOT FOUND"); fail++; continue; }
        FunctionSignatureParser fp = new FunctionSignatureParser(currentProgram.getDataTypeManager(), null);
        FunctionDefinitionDataType fd = fp.parse(f.getSignature(), r[3]);
        new ApplyFunctionSignatureCmd(ad, fd, SourceType.USER_DEFINED, true, true).applyTo(currentProgram);
        if (!r[5].isEmpty()) setPlateComment(ad, r[5]);
        sigs++;
      } catch (Exception ex) { log("sig", r[1], "FAIL " + ex.getMessage()); fail++; }
      finally { currentProgram.endTransaction(tx, true); }
    }
  }

  public void run() throws Exception {
    String[] a = getScriptArgs();
    lib = currentProgram.getName().replaceAll("\\.so$", "");
    rep = new PrintWriter(new FileWriter(a[1], true));
    mergeStructs(); vtables(a[0]); mergeStructs(); signatures(a[0]);
    rep.println(lib + "\tTYPES\tmerged=" + merged + " vtbl=" + vtbls + " vptr=" + vptrs + " sigs=" + sigs + " fail=" + fail); rep.close();
  }
}
