module top (
    input clk,
    input we,
    input [7:0] addr,
    input [3:0] din,
    output logic [3:0] dout
);
  logic [3:0] mem [0:255];
  always_ff @(posedge clk) begin
    if (we) mem[addr] <= din;
    dout <= mem[addr];
  end
endmodule
