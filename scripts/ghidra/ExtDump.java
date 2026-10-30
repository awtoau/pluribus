// Debug (#169): external locations whose label/namespace/original name matches a regex.  args: outFile regex
import ghidra.app.script.GhidraScript;
import ghidra.program.model.symbol.*;
import ghidra.program.model.listing.*;
import java.io.*; import java.util.regex.*;

public class ExtDump extends GhidraScript {
  public void run() throws Exception {
    String[] a = getScriptArgs(); Pattern p = Pattern.compile(a[1]);
    ExternalManager em = currentProgram.getExternalManager();
    try (PrintWriter w = new PrintWriter(new FileWriter(a[0], true))) {
      for (Function f : currentProgram.getFunctionManager().getExternalFunctions()) {
        ExternalLocation el = f.getExternalLocation();
        String s = "EXTFN\t" + f.getName(true) + "\t" + (el == null ? "-" : el.getLabel() + "\t" + el.getOriginalImportedName());
        if (p.matcher(s).find()) w.println(currentProgram.getName() + "\t" + s);
      }
      for (Function f : currentProgram.getFunctionManager().getFunctions(true)) {
        if (f.isThunk() && p.matcher(f.getName(true)).find()) w.println(currentProgram.getName() + "\tTHUNK\t" + f.getName(true) + "\t" + f.getEntryPoint() + "\t" + f.getThunkedFunction(false));
      }
      for (String ln : em.getExternalLibraryNames()) {
        ExternalLocationIterator it = em.getExternalLocations(ln);
        while (it.hasNext()) {
          ExternalLocation el = it.next();
          String s = ln + "\t" + el.getParentNameSpace().getName(true) + "\t" + el.getLabel() + "\t" + el.getOriginalImportedName() + "\t" + (el.getFunction() != null);
          if (p.matcher(s).find()) w.println(currentProgram.getName() + "\t" + s);
        }
      }
    }
  }
}
