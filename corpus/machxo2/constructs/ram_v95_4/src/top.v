module top (clk, we, addr, din, dout);
  input clk;
  input we;
  input [7:0] addr;
  input [3:0] din;
  output [3:0] dout;
  reg [3:0] dout;
  reg [3:0] mem [0:255];
  always @(posedge clk) begin
    if (we) mem[addr] <= din;
    dout <= mem[addr];
  end
endmodule
