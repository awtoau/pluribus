module top (clk, we, addr, din, dout);
  input [0:0] clk;
  input [0:0] we;
  input [7:0] addr;
  input [0:0] din;
  output [0:0] dout;
  reg [0:0] dout;
  (* syn_ramstyle = "block_ram" *) reg [0:0] mem [0:255];
  always @(posedge clk) begin
    if (we) mem[addr] <= din;
    dout <= mem[addr];
  end
endmodule
