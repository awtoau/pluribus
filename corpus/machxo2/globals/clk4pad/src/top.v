module top (
    input wire clk,
    input wire clk1,
    input wire clk2,
    input wire clk3,
    input wire rst,
    input wire ce,
    input wire d,
    output wire q
);
reg [99:0] r0;
always @(posedge clk) if (rst) r0 <= 0; else if (ce) r0 <= {r0[98:0], d};
reg [99:0] r1;
always @(posedge clk1) if (rst) r1 <= 0; else if (ce) r1 <= {r1[98:0], d};
reg [99:0] r2;
always @(posedge clk2) if (rst) r2 <= 0; else if (ce) r2 <= {r2[98:0], d};
reg [99:0] r3;
always @(posedge clk3) if (rst) r3 <= 0; else if (ce) r3 <= {r3[98:0], d};
reg qr; always @(posedge clk) qr <= ^{r0[99], r1[99], r2[99], r3[99]};
assign q = qr;
endmodule
