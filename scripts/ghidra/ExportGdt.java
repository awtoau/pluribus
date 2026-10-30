// Export the /pluribus category (enums, structs, vtbl structs) of the current program to a Data Type Archive (.gdt) for the GUI
// (File > Open File Archive; drag onto a program).  arg0 = output .gdt path.  Names/layouts only.  (#165, #168)
import ghidra.app.script.GhidraScript;
import ghidra.program.model.data.*;
import java.io.File; import java.util.*;

public class ExportGdt extends GhidraScript {
  public void run() throws Exception {
    File f = new File(getScriptArgs()[0]); if (f.exists()) f.delete();
    FileDataTypeManager out = FileDataTypeManager.createFileArchive(f);
    int n = 0;
    int tx = out.startTransaction("export");
    Iterator<DataType> it = currentProgram.getDataTypeManager().getAllDataTypes();
    while (it.hasNext()) {
      DataType d = it.next();
      if (d.getCategoryPath().getPath().startsWith("/pluribus")) { out.resolve(d, DataTypeConflictHandler.REPLACE_HANDLER); n++; }
    }
    out.endTransaction(tx, true); out.save(); out.close();
    println("ExportGdt " + currentProgram.getName() + " types=" + n);
  }
}
