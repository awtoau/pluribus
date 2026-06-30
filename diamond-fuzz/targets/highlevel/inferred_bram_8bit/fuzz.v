module fuzz (
    input  wire clk,
    output reg  out0
);
    reg [7:0] mem [0:255];
    reg [7:0] addr;
    reg [7:0] dout;
    always @(posedge clk) begin
        addr <= addr + 1'b1;
        dout <= mem[addr];
    end
    always @(posedge clk) out0 <= ^dout;
endmodule
