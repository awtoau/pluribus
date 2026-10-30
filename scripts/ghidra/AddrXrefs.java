// References to each given vaddr (and vaddr+0x10 when the arg is a vtable symbol address): from address, containing function.
// args: outFile 0xVADDR ... ; vaddr = ELF vaddr (image base is added).
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;
import ghidra.program.model.symbol.*;
import java.io.*;

public class AddrXrefs extends GhidraScript {
  public void run() throws Exception {
    String[] a = getScriptArgs();
    long base = currentProgram.getImageBase().getOffset();
    try (PrintWriter w = new PrintWriter(new FileWriter(a[0], true))) {
      for (int i = 1; i < a.length; i++) {
        long v = Long.parseLong(a[i].substring(2), 16);
        for (long d : new long[] {0, 0x10}) {
          Address ad = toAddr(base + v + d);
          for (Reference r : getReferencesTo(ad)) {
            Function f = getFunctionContaining(r.getFromAddress());
            w.println(currentProgram.getName() + "\t" + a[i] + "+0x" + Long.toHexString(d) + "\tfrom 0x" + Long.toHexString(r.getFromAddress().getOffset() - base)
              + "\t" + (f == null ? "?" : "0x" + Long.toHexString(f.getEntryPoint().getOffset() - base) + " " + f.getName(true)));
          }
        }
      }
    }
  }
}
