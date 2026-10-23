module top (clk, we, addr, din, dout);
  input clk;
  input we;
  input [7:0] addr;
  input din;
  output dout;
  reg dout;
  (* syn_ramstyle = "block_ram" *) reg mem [0:255];
  always @(posedge clk) begin
    if (we) mem[addr] <= din;
    dout <= mem[addr];
  end
endmodule
