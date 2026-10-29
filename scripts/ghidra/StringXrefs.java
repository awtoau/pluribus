// For defined strings matching a regex: print address, text, and the functions referencing them (vaddr, name).
// args: outFile regex
import ghidra.app.script.GhidraScript;
import ghidra.program.model.data.*;
import ghidra.program.model.listing.*;
import ghidra.program.model.symbol.*;
import java.io.*; import java.util.*; import java.util.regex.*;

public class StringXrefs extends GhidraScript {
  public void run() throws Exception {
    String[] a = getScriptArgs(); Pattern p = Pattern.compile(a[1]);
    long base = currentProgram.getImageBase().getOffset();
    try (PrintWriter w = new PrintWriter(new FileWriter(a[0], true))) {
      DataIterator it = currentProgram.getListing().getDefinedData(true);
      while (it.hasNext()) {
        Data d = it.next();
        if (!(d.getValue() instanceof String)) continue;
        String s = (String) d.getValue();
        if (!p.matcher(s).find()) continue;
        Set<String> fs = new TreeSet<>();
        for (Reference r : getReferencesTo(d.getAddress())) {
          Function f = getFunctionContaining(r.getFromAddress());
          fs.add(f == null ? "?" : "0x" + Long.toHexString(f.getEntryPoint().getOffset() - base) + " " + f.getName(true));
        }
        w.println(currentProgram.getName() + "\t0x" + Long.toHexString(d.getAddress().getOffset() - base) + "\t" + s + "\t" + String.join(" | ", fs));
      }
    }
  }
}
