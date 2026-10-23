// 256x8 simple dual-port synchronous RAM, inferred.
module ram_inferred(input clk, input we, input [7:0] waddr, input [7:0] wdata,
                    input [7:0] raddr, output reg [7:0] rdata);
  reg [7:0] mem [0:255];
  always @(posedge clk) begin
    if (we) mem[waddr] <= wdata;
    rdata <= mem[raddr];
  end
endmodule
