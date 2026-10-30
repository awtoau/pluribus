// Batch decompile to a cache dir, one file per function: <outDir>/<vaddr hex>_<safe name>.c ; existing files are skipped.
// args: outDir selector ... ; selector = "re:<regex>" (full function name, find()), "0xVADDR", or plain substring.
// Output is vendor-derived: keep outDir under vendor-analysis/ (gitignored).
import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.*;
import ghidra.program.model.listing.*;
import java.io.*; import java.util.*; import java.util.regex.*;

public class DecompBatch extends GhidraScript {
  public void run() throws Exception {
    String[] a = getScriptArgs();
    File dir = new File(a[0]); dir.mkdirs();
    long base = currentProgram.getImageBase().getOffset();
    List<Pattern> res = new ArrayList<>(); List<String> subs = new ArrayList<>(); Set<Long> vs = new HashSet<>();
    for (int i = 1; i < a.length; i++) {
      if (a[i].startsWith("re:")) res.add(Pattern.compile(a[i].substring(3)));
      else if (a[i].startsWith("0x")) vs.add(Long.parseLong(a[i].substring(2), 16));
      else subs.add(a[i]);
    }
    DecompInterface di = new DecompInterface(); di.openProgram(currentProgram);
    int done = 0, skipped = 0, failed = 0;
    for (Function f : currentProgram.getFunctionManager().getFunctions(true)) {
      String n = f.getName(true); long v = f.getEntryPoint().getOffset() - base;
      boolean hit = vs.contains(v);
      for (Pattern p : res) if (p.matcher(n).find()) hit = true;
      for (String s : subs) if (n.contains(s)) hit = true;
      if (!hit) continue;
      File out = new File(dir, Long.toHexString(v) + "_" + n.replaceAll("[^A-Za-z0-9_]", "_").replaceAll("_+", "_") + ".c");
      if (out.getName().length() > 200) out = new File(dir, Long.toHexString(v) + "_long.c");
      if (out.exists()) { skipped++; continue; }
      DecompileResults r = di.decompileFunction(f, 60, monitor);
      try (PrintWriter w = new PrintWriter(new FileWriter(out))) {
        w.println("//// " + currentProgram.getName() + " " + n + " @ vaddr 0x" + Long.toHexString(v));
        if (r.decompileCompleted()) { w.println(r.getDecompiledFunction().getC()); done++; }
        else { w.println("// decompile failed"); failed++; }
      }
    }
    println("DecompBatch done=" + done + " skipped=" + skipped + " failed=" + failed);
  }
}
