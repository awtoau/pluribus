module fuzz (
    input wire clk, input wire a, input wire b,
    output wire out_s, out_co
);

wire gnd = 1'b0;
wire s0_w, s1_w, cout_w, s2_w, s3_w;
CCU2D #(
    .INIT0(16'h0666),
    .INIT1(16'h0666),
    .INJECT1_0("YES"),
    .INJECT1_1("YES")
) u0 (
    .CIN(gnd),
    .A0(a), .B0(b), .C0(gnd), .D0(gnd),
    .A1(a), .B1(b), .C1(gnd), .D1(gnd),
    .S0(s0_w), .S1(s1_w), .COUT(cout_w)
);
CCU2D #(
    .INIT0(16'h0666),
    .INIT1(16'h0666),
    .INJECT1_0("YES"),
    .INJECT1_1("YES")
) u1 (
    .CIN(cout_w),
    .A0(a), .B0(b), .C0(gnd), .D0(gnd),
    .A1(a), .B1(b), .C1(gnd), .D1(gnd),
    .S0(s2_w), .S1(s3_w), .COUT()
);
reg [1:0] q;
always @(posedge clk) q <= {s3_w ^ s2_w, s1_w ^ s0_w};
assign {out_co, out_s} = q;

endmodule
