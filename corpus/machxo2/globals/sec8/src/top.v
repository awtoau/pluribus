module top (
    input wire clk,
    input wire ce0,
    input wire rs0,
    input wire ce1,
    input wire rs1,
    input wire ce2,
    input wire rs2,
    input wire ce3,
    input wire rs3,
    input wire ce4,
    input wire rs4,
    input wire ce5,
    input wire rs5,
    input wire ce6,
    input wire rs6,
    input wire ce7,
    input wire rs7,
    input wire d,
    output wire q
);
reg [89:0] r0;
always @(posedge clk) if (rs0) r0 <= 0; else if (ce0) r0 <= {r0[88:0], d ^ r0[89]};
reg [89:0] r1;
always @(posedge clk) if (rs1) r1 <= 0; else if (ce1) r1 <= {r1[88:0], d ^ r0[89]};
reg [89:0] r2;
always @(posedge clk) if (rs2) r2 <= 0; else if (ce2) r2 <= {r2[88:0], d ^ r1[89]};
reg [89:0] r3;
always @(posedge clk) if (rs3) r3 <= 0; else if (ce3) r3 <= {r3[88:0], d ^ r2[89]};
reg [89:0] r4;
always @(posedge clk) if (rs4) r4 <= 0; else if (ce4) r4 <= {r4[88:0], d ^ r3[89]};
reg [89:0] r5;
always @(posedge clk) if (rs5) r5 <= 0; else if (ce5) r5 <= {r5[88:0], d ^ r4[89]};
reg [89:0] r6;
always @(posedge clk) if (rs6) r6 <= 0; else if (ce6) r6 <= {r6[88:0], d ^ r5[89]};
reg [89:0] r7;
always @(posedge clk) if (rs7) r7 <= 0; else if (ce7) r7 <= {r7[88:0], d ^ r6[89]};
reg qr; always @(posedge clk) qr <= ^{r0[89], r1[89], r2[89], r3[89], r4[89], r5[89], r6[89], r7[89]};
assign q = qr;
endmodule
