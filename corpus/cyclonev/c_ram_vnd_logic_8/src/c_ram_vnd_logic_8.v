module c_ram_vnd_logic_8 (clk, we, waddr, raddr, din, dout);
  input clk, we;
  input [5:0] waddr, raddr;
  input [7:0] din;
  output [7:0] dout;
  reg [7:0] dout;
  (* ramstyle = "logic" *) reg [7:0] mem [0:63];
  always @(posedge clk) begin
    if (we) mem[waddr] <= din;
    dout <= mem[raddr];
  end
endmodule
