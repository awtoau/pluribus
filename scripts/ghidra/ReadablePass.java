// Rename locals/params from types and struct field accesses, retype locals from field types (so enum constants render
// as names), then export annotated pseudo-code per class.  (#165, #168)
// args: outDir mode(rename|export|both) selector[;selector...] [limit]
//   selector = "re:<regex>" over the full function name, "0xVADDR", or substring.  mode rename = DB writes only (no -readOnly).
// Output (export) is vendor-derived: outDir must be under vendor-analysis/ (gitignored).
import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.*;
import ghidra.program.model.address.*;
import ghidra.program.model.data.*;
import ghidra.program.model.listing.*;
import ghidra.program.model.pcode.*;
import ghidra.program.model.symbol.*;
import java.io.*; import java.util.*; import java.util.regex.*;

public class ReadablePass extends GhidraScript {
  static final Pattern DEFAULT_NAME = Pattern.compile("(param_\\d+|[a-zA-Z]{1,5}Var\\d+|local_[0-9a-fA-F]+|[a-zA-Z]+Stack_?[0-9a-fA-F]+|in_.*)");
  static final Map<String, String> TYPE_NAMES = new HashMap<>();
  static {
    TYPE_NAMES.put("CDB_ATOM_NODE", "atom"); TYPE_NAMES.put("ASMDB_SETTING_STREAMS", "streams");
    TYPE_NAMES.put("ASM_ARCH_GROUP", "group"); TYPE_NAMES.put("ASMDB_ARCH_GROUP_BASE", "group_db");
    TYPE_NAMES.put("PDB_SEGMENT_TEMPLATE", "seg"); TYPE_NAMES.put("PDB_SEGMENT_READER", "reader");
    TYPE_NAMES.put("ASM_BITFIELD", "bitfield"); TYPE_NAMES.put("ASMCC_CHIP_MODEL", "chip");
    TYPE_NAMES.put("QTL_BOOL_VECTOR", "bools"); TYPE_NAMES.put("CDB_RE_NODE", "re_node");
  }
  long base; int renamed = 0, retyped = 0, failed = 0, exported = 0;
  Map<String, StringBuilder> classes = new TreeMap<>(); Map<String, Set<String>> classTypes = new HashMap<>();
  Set<String> enumNames = new TreeSet<>();

  DataType strip(DataType dt) {
    while (true) {
      if (dt instanceof Pointer) dt = ((Pointer) dt).getDataType();
      else if (dt instanceof TypeDef) dt = ((TypeDef) dt).getBaseDataType();
      else if (dt instanceof Array) dt = ((Array) dt).getDataType();
      else return dt;
      if (dt == null) return null;
    }
  }
  String nameFromType(DataType dt) {
    if (!(dt instanceof Pointer)) return null;
    DataType b = strip(dt);
    if (!(b instanceof Structure) && !(b instanceof Composite)) return null;
    String n = b.getName();
    if (n.contains("<") || n.startsWith("undefined")) return null;
    if (TYPE_NAMES.containsKey(n)) return TYPE_NAMES.get(n);
    String[] t = n.toLowerCase().split("_");
    if (t.length > 1) return String.join("_", Arrays.copyOfRange(t, 1, t.length));
    return t[0];
  }
  String uniq(Set<String> used, String n) {
    n = n.replaceAll("[^A-Za-z0-9_]", "_"); String c = n; int i = 2;
    while (used.contains(c)) c = n + "_" + i++;
    used.add(c); return c;
  }

  void renamePass(Function f, HighFunction hf) {
    Set<String> used = new HashSet<>();
    Iterator<HighSymbol> it = hf.getLocalSymbolMap().getSymbols();
    List<HighSymbol> syms = new ArrayList<>();
    while (it.hasNext()) { HighSymbol s = it.next(); syms.add(s); used.add(s.getName()); }
    Map<HighSymbol, String> newName = new LinkedHashMap<>(); Map<HighSymbol, DataType> newType = new HashMap<>();
    // 1. field accesses: LOAD(PTRSUB/PTRADD(structptr, const)) -> name + type of the field
    Iterator<PcodeOpAST> ops = hf.getPcodeOps();
    while (ops.hasNext()) {
      PcodeOpAST op = ops.next();
      if (op.getOpcode() != PcodeOp.LOAD || op.getOutput() == null) continue;
      HighVariable hv = op.getOutput().getHigh();
      if (hv == null || hv.getSymbol() == null) continue;
      HighSymbol hs = hv.getSymbol();
      Varnode addr = op.getInput(1); PcodeOp d = addr.getDef();
      if (d == null || (d.getOpcode() != PcodeOp.PTRSUB && d.getOpcode() != PcodeOp.PTRADD)) continue;
      if (!d.getInput(1).isConstant()) continue;
      HighVariable bh = d.getInput(0).getHigh(); if (bh == null) continue;
      DataType pt = bh.getDataType();
      if (!(pt instanceof Pointer) || !(((Pointer) pt).getDataType() instanceof Structure)) continue;
      Structure st = (Structure) ((Pointer) pt).getDataType();
      int off = (int) d.getInput(1).getOffset();
      DataTypeComponent c = st.getComponentAt(off);
      if (c == null || c.getFieldName() == null || c.getOffset() != off) continue;
      if (!hs.isParameter() && DEFAULT_NAME.matcher(hs.getName()).matches() && !newName.containsKey(hs)) {
        String fn = c.getFieldName().replaceFirst("^m_", "");
        newName.put(hs, fn);
      }
      DataType ft = c.getDataType();
      if ((strip(ft) instanceof ghidra.program.model.data.Enum) && !hs.isParameter() && !(hs.getDataType().getName().equals(ft.getName())))
        newType.put(hs, ft);
    }
    // 2. pointer-to-struct params/locals by type
    for (HighSymbol s : syms) {
      if (newName.containsKey(s) || !DEFAULT_NAME.matcher(s.getName()).matches() || s.getName().equals("this")) continue;
      String n = nameFromType(s.getDataType());
      if (n != null) newName.put(s, n);
    }
    Set<HighSymbol> all = new LinkedHashSet<>(newName.keySet()); all.addAll(newType.keySet());
    for (HighSymbol s : all) {
      try {
        String n = newName.containsKey(s) ? uniq(used, newName.get(s)) : null;
        DataType t = newType.get(s);
        HighFunctionDBUtil.updateDBVariable(s, n, t, SourceType.USER_DEFINED);
        if (n != null) renamed++;
        if (t != null) retyped++;
      } catch (Exception e) { failed++; }
    }
  }

  void collectTypes(HighFunction hf, Set<String> out) {
    Iterator<HighSymbol> it = hf.getLocalSymbolMap().getSymbols();
    while (it.hasNext()) {
      DataType b = strip(it.next().getDataType());
      if (b instanceof Structure || b instanceof ghidra.program.model.data.Enum) {
        String n = b.getName(); if (!n.startsWith("undefined") && !n.contains("<")) out.add((b instanceof Structure ? "struct " : "enum ") + n);
      }
    }
  }
  String names(Set<Function> fs, int max) {
    List<String> l = new ArrayList<>();
    for (Function g : fs) l.add(g.getName(true) + "@" + Long.toHexString(g.getEntryPoint().getOffset() - base));
    Collections.sort(l);
    return l.size() > max ? String.join(", ", l.subList(0, max)) + ", ... (" + l.size() + ")" : String.join(", ", l);
  }

  public void run() throws Exception {
    String[] a = getScriptArgs();
    File out = new File(a[0]); String mode = a[1];
    int limit = a.length > 3 ? Integer.parseInt(a[3]) : Integer.MAX_VALUE;
    List<Pattern> res = new ArrayList<>(); List<String> subs = new ArrayList<>(); Set<Long> vs = new HashSet<>();
    for (String s : a[2].split(";")) {
      if (s.startsWith("re:")) res.add(Pattern.compile(s.substring(3)));
      else if (s.startsWith("0x")) vs.add(Long.parseLong(s.substring(2), 16));
      else if (!s.isEmpty()) subs.add(s);
    }
    base = currentProgram.getImageBase().getOffset();
    String lib = currentProgram.getName().replaceAll("\\.so$", "");
    boolean doRename = !mode.equals("export"), doExport = !mode.equals("rename");
    DecompInterface di = new DecompInterface(); di.openProgram(currentProgram);
    int n = 0;
    for (Function f : currentProgram.getFunctionManager().getFunctions(true)) {
      if (n >= limit) break;
      String fn = f.getName(true); long v = f.getEntryPoint().getOffset() - base;
      boolean hit = vs.contains(v);
      for (Pattern p : res) if (p.matcher(fn).find()) hit = true;
      for (String s : subs) if (fn.contains(s)) hit = true;
      if (!hit || f.isThunk() || f.isExternal()) continue;
      n++;
      DecompileResults r = di.decompileFunction(f, 60, monitor);
      if (!r.decompileCompleted()) { failed++; continue; }
      if (doRename) {
        int tx = currentProgram.startTransaction("readable-rename");
        int before = renamed + retyped;
        try { renamePass(f, r.getHighFunction()); } catch (Exception e) { failed++; }
        finally { currentProgram.endTransaction(tx, true); }
        if (doExport && renamed + retyped > before) { r = di.decompileFunction(f, 60, monitor); if (!r.decompileCompleted()) { failed++; continue; } }
      }
      if (!doExport) continue;
      String cls = f.getParentNamespace().isGlobal() ? "_global" : f.getParentNamespace().getName(true).replace("::", ".");
      cls = cls.replaceAll("[^A-Za-z0-9_.]", "_");
      if (cls.length() > 120) cls = cls.substring(0, 120);
      Set<String> tys = classTypes.computeIfAbsent(cls, k -> new TreeSet<>());
      collectTypes(r.getHighFunction(), tys);
      StringBuilder sb = classes.computeIfAbsent(cls, k -> new StringBuilder());
      sb.append("//// ").append(fn).append(" @ vaddr 0x").append(Long.toHexString(v)).append("\n");
      sb.append("// callers: ").append(names(f.getCallingFunctions(monitor), 12)).append("\n");
      sb.append("// callees: ").append(names(f.getCalledFunctions(monitor), 20)).append("\n");
      sb.append(r.getDecompiledFunction().getC()).append("\n");
      exported++;
    }
    if (doExport) {
      File d = new File(out, lib); d.mkdirs();
      for (var e : classes.entrySet()) {
        try (PrintWriter w = new PrintWriter(new FileWriter(new File(d, e.getKey() + ".c")))) {
          w.println("// lib: " + lib + "   class: " + e.getKey() + "   (annotated pseudo-code, vendor-derived: do not commit)");
          w.println("// types used: " + String.join(", ", classTypes.get(e.getKey())));
          w.println(); w.print(e.getValue());
        }
      }
    }
    println("ReadablePass " + lib + " functions=" + n + " renamed=" + renamed + " retyped=" + retyped + " failed=" + failed + " exported=" + exported + " classfiles=" + classes.size());
  }
}
