module top (
    input wire clk,
    input wire x0,
    input wire x1,
    input wire x2,
    input wire x3,
    input wire d,
    output wire q
);
reg [239:0] r;
always @(posedge clk) r <= {r[238:0], d} ^ ({60{x0}} & r[239:180]) ^ ({60{x1}} & r[179:120]) ^ ({60{x2}} & r[119:60]) ^ ({60{x3}} & r[59:0]) ^ {r[238:0], 1'b0};
reg qr; always @(posedge clk) qr <= r[239];
assign q = qr;
endmodule
