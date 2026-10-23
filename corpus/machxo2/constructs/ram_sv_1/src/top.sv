module top (
    input clk,
    input we,
    input [7:0] addr,
    input din,
    output logic dout
);
  logic mem [0:255];
  always_ff @(posedge clk) begin
    if (we) mem[addr] <= din;
    dout <= mem[addr];
  end
endmodule
