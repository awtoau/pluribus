module fuzz(input wire clk,output wire out0);
 wire g=1'b0;
 wire a,b,c,d,e,f;
 JTAGF #(.ER1("ENABLED"),.ER2("DISABLED")) u(.TCK(),.TMS(),.TDI(),.JTDO1(g),.JTDO2(g),.TDO(),.JTCK(a),.JTDI(b),.JSHIFT(c),.JUPDATE(d),.JRSTN(e),.JCE1(f),.JCE2(),.JRTI1(),.JRTI2());
 reg r; always @(posedge clk) r<=a^b^c^d^e^f; assign out0=r;
endmodule
