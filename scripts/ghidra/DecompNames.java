// Decompile functions whose full name contains a pattern, or whose vaddr is listed. args: outFile pattern-or-0xVADDR ...
// Output is vendor-derived: keep it under vendor-analysis/ (gitignored).
import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.*;
import ghidra.program.model.listing.*;
import java.io.*; import java.util.*;

public class DecompNames extends GhidraScript {
  public void run() throws Exception {
    String[] a = getScriptArgs();
    long base = currentProgram.getImageBase().getOffset();
    DecompInterface di = new DecompInterface(); di.openProgram(currentProgram);
    try (PrintWriter w = new PrintWriter(new FileWriter(a[0], true))) {
      for (Function f : currentProgram.getFunctionManager().getFunctions(true)) {
        String n = f.getName(true); long v = f.getEntryPoint().getOffset() - base;
        boolean hit = false;
        for (int i = 1; i < a.length; i++) {
          if (a[i].startsWith("0x")) { if (Long.parseLong(a[i].substring(2), 16) == v) hit = true; }
          else if (n.contains(a[i])) hit = true;
        }
        if (!hit) continue;
        DecompileResults r = di.decompileFunction(f, 90, monitor);
        w.println("//// " + currentProgram.getName() + " " + n + " @ vaddr 0x" + Long.toHexString(v));
        w.println(r.decompileCompleted() ? r.getDecompiledFunction().getC() : "// decompile failed");
      }
    }
  }
}
