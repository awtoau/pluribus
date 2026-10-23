module top (
    input clk,
    input we,
    input [7:0] addr,
    input [7:0] din,
    output logic [7:0] dout
);
  logic [7:0] mem [0:255];
  always_ff @(posedge clk) begin
    if (we) mem[addr] <= din;
    dout <= mem[addr];
  end
endmodule
