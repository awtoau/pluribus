module top (
    input clk,
    input we,
    input [7:0] addr,
    input [15:0] din,
    output logic [15:0] dout
);
  logic [15:0] mem [0:255];
  always_ff @(posedge clk) begin
    if (we) mem[addr] <= din;
    dout <= mem[addr];
  end
endmodule
