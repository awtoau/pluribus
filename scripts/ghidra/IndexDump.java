// Index feed (#169): functions, call edges, string xrefs of one program -> TSV for scripts/ghidra_index.py.
// args: outDir (one <program>.tsv per program).   Rows: F vaddr size name | E caller_vaddr callee_vaddr | S func_vaddr str_vaddr text | R func_vaddr data_vaddr (non-string data ref)
// vaddr = Ghidra address - image base (= ELF/nm address).  Values only; stays under vendor-analysis/.
import ghidra.app.script.GhidraScript;
import ghidra.program.model.listing.*;
import ghidra.program.model.symbol.*;
import ghidra.program.model.address.*;
import java.io.*; import java.util.*;

public class IndexDump extends GhidraScript {
  public void run() throws Exception {
    String[] a = getScriptArgs();
    long base = currentProgram.getImageBase().getOffset();
    ReferenceManager rm = currentProgram.getReferenceManager();
    Listing li = currentProgram.getListing();
    try (PrintWriter w = new PrintWriter(new BufferedWriter(new FileWriter(new File(a[0], currentProgram.getName().replaceAll("\\.so$", "") + ".tsv"))))) {
      FunctionIterator fi = currentProgram.getFunctionManager().getFunctions(true);
      while (fi.hasNext()) {
        Function f = fi.next();
        if (f.isExternal()) continue;
        long fv = f.getEntryPoint().getOffset() - base;
        w.println("F\t" + Long.toHexString(fv) + "\t" + f.getBody().getNumAddresses() + "\t" + f.getName(true));
        Set<String> seen = new HashSet<>();
        AddressIterator ai = f.getBody().getAddresses(true);
        for (Address ad : ai) {
          for (Reference r : rm.getReferencesFrom(ad)) {
            if (!r.isMemoryReference()) continue;
            Address to = r.getToAddress();
            if (r.getReferenceType().isCall() || r.getReferenceType().isJump() && !f.getBody().contains(to)) {
              Function g = getFunctionAt(to);
              if (g != null && g.isThunk() && g.getThunkedFunction(true) != null) g = g.getThunkedFunction(true);
              if (g == null) continue;
              String k = "E\t" + Long.toHexString(fv) + "\t" + (g.isExternal() ? "ext:" + g.getName() : Long.toHexString(g.getEntryPoint().getOffset() - base));
              if (seen.add(k)) w.println(k);
            } else if (r.getReferenceType().isData() || r.getReferenceType().isRead()) {
              Data d = li.getDataAt(to);
              if (d == null) { d = li.getDataContaining(to); }
              if (d == null) continue;
              long dv = d.getAddress().getOffset() - base;
              if (d.getValue() instanceof String) {
                String s = (String) d.getValue();
                if (s.length() < 3) continue;
                String k = "S\t" + Long.toHexString(fv) + "\t" + Long.toHexString(dv) + "\t" + s.replace("\\", "\\\\").replace("\t", "\\t").replace("\n", "\\n");
                if (seen.add(k)) w.println(k.length() > 400 ? k.substring(0, 400) : k);
              } else {
                String k = "R\t" + Long.toHexString(fv) + "\t" + Long.toHexString(dv);
                if (seen.add(k)) w.println(k);
              }
            }
          }
        }
      }
    }
  }
}
