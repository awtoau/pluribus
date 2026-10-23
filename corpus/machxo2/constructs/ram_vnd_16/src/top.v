module top (clk, we, addr, din, dout);
  input clk;
  input we;
  input [7:0] addr;
  input [15:0] din;
  output [15:0] dout;
  reg [15:0] dout;
  (* syn_ramstyle = "block_ram" *) reg [15:0] mem [0:255];
  always @(posedge clk) begin
    if (we) mem[addr] <= din;
    dout <= mem[addr];
  end
endmodule
