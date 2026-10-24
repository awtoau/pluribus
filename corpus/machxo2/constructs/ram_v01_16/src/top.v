module top (
    input [0:0] clk,
    input [0:0] we,
    input [7:0] addr,
    input [15:0] din,
    output reg [15:0] dout
);
  localparam DEPTH = 256;
  reg [15:0] mem [0:DEPTH-1];
  always @(posedge clk) begin
    if (we) mem[addr] <= din;
    dout <= mem[addr];
  end
endmodule
