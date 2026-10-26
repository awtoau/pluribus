// 16 arbitrary 6-input functions (fixed 64-bit truth tables), each over a rotated
// slice of 8 inputs.  Gives the LUT-mask comparison many dense, asymmetric masks.
module lut_random(input [7:0] x, output [15:0] y);
  localparam [64*16-1:0] TT = {
    64'h9E3779B97F4A7C15, 64'hBF58476D1CE4E5B9, 64'h94D049BB133111EB, 64'h2545F4914F6CDD1D,
    64'hD6E8FEB86659FD93, 64'hA0761D6478BD642F, 64'hE7037ED1A0B428DB, 64'h8EBC6AF09C88C6E3,
    64'h589965CC75374CC3, 64'h1D8E4E27C47D124F, 64'hC2B2AE3D27D4EB4F, 64'h165667B19E3779F9,
    64'h27D4EB2F165667C5, 64'h85EBCA77C2B2AE63, 64'hFF51AFD7ED558CCD, 64'hC4CEB9FE1A85EC53};
  genvar k;
  generate for (k = 0; k < 16; k = k + 1) begin : g
    wire [7:0] r = {x, x} >> (k % 8);
    wire [5:0] sel = (k < 8) ? r[5:0] : {r[0], r[2], r[4], r[1], r[3], r[5]};
    assign y[k] = TT[64*k + sel];
  end endgenerate
endmodule
