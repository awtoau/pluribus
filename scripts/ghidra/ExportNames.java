// Dumps user-defined function / data names and pluribus bookmarks of currentProgram as TSV rows (vaddr = addr - image base).
// arg0 = output file (appended).  Merge the rows into reference/ghidra/*.tsv by hand, adding the source column.
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;
import ghidra.program.model.symbol.*;
import java.io.*;

public class ExportNames extends GhidraScript {
  public void run() throws Exception {
    String lib = currentProgram.getName().replaceAll("\\.so$", "");
    long base = currentProgram.getImageBase().getOffset();
    try (PrintWriter w = new PrintWriter(new FileWriter(getScriptArgs()[0], true))) {
      for (Function f : currentProgram.getFunctionManager().getFunctions(true)) {
        if (f.getSymbol().getSource() != SourceType.USER_DEFINED) continue;
        w.println("functions\t" + lib + "\t" + Long.toHexString(f.getEntryPoint().getOffset() - base) + "\t" + f.getName(true) + "\t" + f.getPrototypeString(false, false) + "\t\t");
      }
      SymbolIterator it = currentProgram.getSymbolTable().getSymbolIterator(true);
      while (it.hasNext()) {
        Symbol s = it.next();
        if (s.getSource() != SourceType.USER_DEFINED || s.getSymbolType() != SymbolType.LABEL) continue;
        Data d = currentProgram.getListing().getDataAt(s.getAddress());
        w.println("globals\t" + lib + "\t" + Long.toHexString(s.getAddress().getOffset() - base) + "\t" + s.getName() + "\t" + (d == null ? "" : d.getDataType().getName()) + "\t\t\t");
      }
      BookmarkManager bm = currentProgram.getBookmarkManager();
      var bi = bm.getBookmarksIterator();
      while (bi.hasNext()) {
        Bookmark b = bi.next();
        if (!b.getCategory().equals("pluribus")) continue;
        w.println("notes\t" + lib + "\t" + Long.toHexString(b.getAddress().getOffset() - base) + "\tbookmark\t" + b.getComment() + "\t");
      }
    }
  }
}
