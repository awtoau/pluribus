// P-code emulation of a pure function over an argument sweep: value -> return table from the code itself.  (#165, #168)
// args: outFile vaddr maxSteps argSpec ...   argSpec = N | 0xN | A..B (inclusive); up to 6 integer args (RDI RSI RDX RCX R8 R9).
// Output TSV: lib, vaddr, arg1..argN, rax, status(ok|steps|fault:<where>).  Calls into imports/PLT stop the run (status fault:call).
// Values only (no bodies).  Keep under vendor-analysis/ (derived from a vendor binary).
import ghidra.app.script.GhidraScript;
import ghidra.app.emulator.EmulatorHelper;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;
import java.io.*; import java.util.*;

public class Emulate extends GhidraScript {
  static final String[] REGS = {"RDI", "RSI", "RDX", "RCX", "R8", "R9"};
  static final long STACK = 0x7ff00000L, SENTINEL = 0x1000L;
  public void run() throws Exception {
    String[] a = getScriptArgs();
    String lib = currentProgram.getName().replaceAll("\\.so$", "");
    Address entry = currentProgram.getImageBase().add(Long.decode(a[1]));
    long maxSteps = Long.parseLong(a[2]);
    int n = a.length - 3; long[][] rng = new long[n][2];
    for (int i = 0; i < n; i++) {
      String s = a[3 + i];
      if (s.contains("..")) { rng[i][0] = Long.decode(s.split("\\.\\.")[0]); rng[i][1] = Long.decode(s.split("\\.\\.")[1]); }
      else rng[i][0] = rng[i][1] = Long.decode(s);
    }
    Function f = currentProgram.getFunctionManager().getFunctionAt(entry);
    AddressSet body = f == null ? null : new AddressSet(f.getBody());
    EmulatorHelper emu = new EmulatorHelper(currentProgram);
    long[] cur = new long[n]; for (int i = 0; i < n; i++) cur[i] = rng[i][0];
    try (PrintWriter w = new PrintWriter(new FileWriter(a[0], true))) {
      boolean done = false;
      while (!done) {
        String status = "ok"; long rax = 0;
        try {
          emu.writeRegister("RSP", STACK); emu.writeRegister("RBP", STACK);
          emu.writeMemory(currentProgram.getAddressFactory().getDefaultAddressSpace().getAddress(STACK), new byte[8]);   // return addr = SENTINEL (LE)
          emu.writeMemory(currentProgram.getAddressFactory().getDefaultAddressSpace().getAddress(STACK), new byte[]{0, 0x10, 0, 0, 0, 0, 0, 0});
          for (int i = 0; i < n && i < 6; i++) emu.writeRegister(REGS[i], cur[i]);
          emu.writeRegister(emu.getPCRegister(), entry.getOffset());
          long steps = 0;
          while (true) {
            long pc = emu.getExecutionAddress().getOffset();
            if (pc == SENTINEL) break;
            Address pa = emu.getExecutionAddress();
            Function g = getFunctionAt(pa);
            if (g != null && !pa.equals(entry)) { status = "fault:call"; break; }   // entered another function (call / tail call)
            if (currentProgram.getMemory().getBlock(pa) == null) { status = "fault:pc"; break; }
            if (++steps > maxSteps) { status = "steps"; break; }
            if (!emu.step(monitor)) { status = "fault:" + emu.getLastError(); break; }
          }
          rax = emu.readRegister("RAX").longValue();
        } catch (Exception e) { status = "fault:" + e.getMessage(); }
        StringBuilder sb = new StringBuilder(lib + "\t" + a[1]);
        for (int i = 0; i < n; i++) sb.append("\t").append(cur[i]);
        sb.append("\t").append(rax).append("\t").append(status.replace('\t', ' ').replace('\n', ' '));
        w.println(sb);
        int k = n - 1;
        while (k >= 0 && ++cur[k] > rng[k][1]) { cur[k] = rng[k][0]; k--; }
        if (k < 0) done = true;
      }
    }
  }
}
