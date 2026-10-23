module top (
    input [0:0] clk,
    input [0:0] we,
    input [7:0] addr,
    input [3:0] din,
    output reg [3:0] dout
);
  localparam DEPTH = 256;
  reg [3:0] mem [0:DEPTH-1];
  always @(posedge clk) begin
    if (we) mem[addr] <= din;
    dout <= mem[addr];
  end
endmodule
