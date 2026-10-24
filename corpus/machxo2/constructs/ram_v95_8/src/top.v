module top (clk, we, addr, din, dout);
  input clk;
  input we;
  input [7:0] addr;
  input [7:0] din;
  output [7:0] dout;
  reg [7:0] dout;
  reg [7:0] mem [0:255];
  always @(posedge clk) begin
    if (we) mem[addr] <= din;
    dout <= mem[addr];
  end
endmodule
