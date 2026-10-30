// All references to each target (function/data symbol regex, or 0xVADDR): referencing function, address, ref type, and for
// functions the call-site count.  args: outFile target ...   target = "re:<regex>" over symbol names | "0xVADDR" | exact name.
// Output TSV: lib, target, target_vaddr, from_vaddr, from_function, ref_type.  Names/addresses only; keep under vendor-analysis/.
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.*;
import ghidra.program.model.symbol.*;
import ghidra.program.model.listing.*;
import java.io.*; import java.util.*; import java.util.regex.*;

public class FindXrefs extends GhidraScript {
  public void run() throws Exception {
    String[] a = getScriptArgs();
    long base = currentProgram.getImageBase().getOffset();
    String lib = currentProgram.getName().replaceAll("\\.so$", "");
    try (PrintWriter w = new PrintWriter(new FileWriter(a[0], true))) {
      for (int i = 1; i < a.length; i++) {
        List<Symbol> targets = new ArrayList<>();
        if (a[i].startsWith("0x")) {
          Address ad = currentProgram.getImageBase().add(Long.parseLong(a[i].substring(2), 16));
          Symbol s = currentProgram.getSymbolTable().getPrimarySymbol(ad);
          if (s != null) targets.add(s);
        } else {
          Pattern p = a[i].startsWith("re:") ? Pattern.compile(a[i].substring(3)) : null;
          SymbolIterator it = currentProgram.getSymbolTable().getAllSymbols(true);
          while (it.hasNext()) {
            Symbol s = it.next(); String n = s.getName(true);
            if (p != null ? p.matcher(n).find() : n.equals(a[i])) targets.add(s);
          }
        }
        for (Symbol s : targets) {
          for (Reference r : getReferencesTo(s.getAddress())) {
            Function f = getFunctionContaining(r.getFromAddress());
            w.println(lib + "\t" + s.getName(true) + "\t0x" + Long.toHexString(s.getAddress().getOffset() - base) + "\t0x"
              + Long.toHexString(r.getFromAddress().getOffset() - base) + "\t" + (f == null ? "?" : f.getName(true)) + "\t" + r.getReferenceType());
          }
        }
      }
    }
  }
}
