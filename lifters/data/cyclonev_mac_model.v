// Own behavioural model of the Cyclone V variable-precision DSP atom `cyclonev_mac`.
// The vendor atom wraps cyclonev_mac_encrypted (not distributed in plain text); this module has the
// same ports and parameters so a Quartus post-fit netlist (build.vo) and the lifted netlist can run on it.
// Source of behaviour: Cyclone V Device Handbook Vol. 1 ch. 3 (sources/cyclonev-device-handbook.pdf) for the
// block architecture; parameter meaning inferred from corpus build.vo defparams and validated by
// scripts/cyclonev_dsp_model_check.py (build.vo on this model vs the design's source RTL).
// Modelled: independent multiplies m9x9 (lane 0), m18x18_full, m27x27; m18x18_sumof2; per-operand input
// registers and the output register (clock "none" | "0" | "1" | "2", enable ena[n]).
// Not modelled (result is X, never a guess): other operation modes, pre-adder, coefficients,
// accumulate / chainout / scan chains, aclr (any asserted aclr gives X results), m9x9 lanes 1-2.
`timescale 1ps/1ps
module cyclonev_mac (
    ax, ay, az, coefsela, bx, by, bz, coefselb, scanin, chainin, loadconst, accumulate, negate, sub,
    clk, ena, aclr, resulta, resultb, scanout, chainout, dftout);
parameter ax_width = 16;
parameter ay_scan_in_width = 16;
parameter az_width = 1;
parameter bx_width = 16;
parameter by_width = 16;
parameter bz_width = 1;
parameter scan_out_width = 1;
parameter result_a_width = 33;
parameter result_b_width = 1;
parameter operation_mode = "m18x18_sumof2";
parameter mode_sub_location = 0;
parameter operand_source_max = "input";
parameter operand_source_may = "input";
parameter operand_source_mbx = "input";
parameter operand_source_mby = "input";
parameter preadder_subtract_a = "false";
parameter preadder_subtract_b = "false";
parameter signed_max = "false";
parameter signed_may = "false";
parameter signed_mbx = "false";
parameter signed_mby = "false";
parameter ay_use_scan_in = "false";
parameter by_use_scan_in = "false";
parameter delay_scan_out_ay = "false";
parameter delay_scan_out_by = "false";
parameter use_chainadder = "false";
parameter enable_double_accum = "false";
parameter [5:0] load_const_value = 6'b0;
parameter signed [26:0] coef_a_0 = 0;
parameter signed [26:0] coef_a_1 = 0;
parameter signed [26:0] coef_a_2 = 0;
parameter signed [26:0] coef_a_3 = 0;
parameter signed [26:0] coef_a_4 = 0;
parameter signed [26:0] coef_a_5 = 0;
parameter signed [26:0] coef_a_6 = 0;
parameter signed [26:0] coef_a_7 = 0;
parameter signed [17:0] coef_b_0 = 0;
parameter signed [17:0] coef_b_1 = 0;
parameter signed [17:0] coef_b_2 = 0;
parameter signed [17:0] coef_b_3 = 0;
parameter signed [17:0] coef_b_4 = 0;
parameter signed [17:0] coef_b_5 = 0;
parameter signed [17:0] coef_b_6 = 0;
parameter signed [17:0] coef_b_7 = 0;
parameter ax_clock = "none";
parameter ay_scan_in_clock = "none";
parameter az_clock = "none";
parameter bx_clock = "none";
parameter by_clock = "none";
parameter bz_clock = "none";
parameter coef_sel_a_clock = "none";
parameter coef_sel_b_clock = "none";
parameter sub_clock = "none";
parameter negate_clock = "none";
parameter accumulate_clock = "none";
parameter load_const_clock = "none";
parameter output_clock = "none";

input sub, negate, accumulate, loadconst;
input [ax_width-1:0] ax;
input [ay_scan_in_width-1:0] ay;
input [ay_scan_in_width-1:0] scanin;
input [az_width-1:0] az;
input [bx_width-1:0] bx;
input [by_width-1:0] by;
input [bz_width-1:0] bz;
input [2:0] coefsela, coefselb, clk, ena;
input [1:0] aclr;
input [63:0] chainin;
output [result_a_width-1:0] resulta;
output [result_b_width-1:0] resultb;
output [scan_out_width-1:0] scanout;
output [63:0] chainout;
output dftout;

// registered operand: clock string "0" | "1" | "2" selects clk[n] / ena[n]
function integer cidx(input [8*4-1:0] s);
    cidx = (s == "0") ? 0 : (s == "1") ? 1 : (s == "2") ? 2 : -1;
endfunction

reg [ax_width-1:0] r_ax = 0;
reg [ay_scan_in_width-1:0] r_ay = 0;
reg [bx_width-1:0] r_bx = 0;
reg [by_width-1:0] r_by = 0;
reg [63:0] r_out = 0;

localparam integer CAX = cidx(ax_clock), CAY = cidx(ay_scan_in_clock), CBX = cidx(bx_clock),
                   CBY = cidx(by_clock), COUT = cidx(output_clock);

generate
    if (CAX >= 0) always @(posedge clk[CAX]) if (ena[CAX]) r_ax <= ax;
    if (CAY >= 0) always @(posedge clk[CAY]) if (ena[CAY]) r_ay <= ay;
    if (CBX >= 0) always @(posedge clk[CBX]) if (ena[CBX]) r_bx <= bx;
    if (CBY >= 0) always @(posedge clk[CBY]) if (ena[CBY]) r_by <= by;
endgenerate

wire [ax_width-1:0] e_ax = (CAX >= 0) ? r_ax : ax;
wire [ay_scan_in_width-1:0] e_ay = (CAY >= 0) ? r_ay : ay;
wire [bx_width-1:0] e_bx = (CBX >= 0) ? r_bx : bx;
wire [by_width-1:0] e_by = (CBY >= 0) ? r_by : by;

// operands extended to 64 bits by the operand's own signedness
wire signed [63:0] sx_ax = (signed_max == "true") ? {{64{e_ax[ax_width-1]}}, e_ax} : {64'b0, e_ax};
wire signed [63:0] sx_ay = (signed_may == "true") ? {{64{e_ay[ay_scan_in_width-1]}}, e_ay} : {64'b0, e_ay};
wire signed [63:0] sx_bx = (signed_mbx == "true") ? {{64{e_bx[bx_width-1]}}, e_bx} : {64'b0, e_bx};
wire signed [63:0] sx_by = (signed_mby == "true") ? {{64{e_by[by_width-1]}}, e_by} : {64'b0, e_by};

wire any_aclr = |aclr;
wire m9 = (operation_mode == "m9x9");
wire m18 = (operation_mode == "m18x18_full");
wire m27 = (operation_mode == "m27x27");
wire s2 = (operation_mode == "m18x18_sumof2");
wire supported = (m9 || m18 || m27 || s2) && !any_aclr && !(loadconst | accumulate | negate | sub)
                 && (use_chainadder == "false") && (enable_double_accum == "false");
// m9x9 lane 0: 18-bit product in resulta[17:0]; above it the vendor atom gives all-ones iff both operands are
// signed and negative, else 0 (measured: scripts/cyclonev_dsp_vendor_check.py, issue #121);
// m9x9 with operands wider than 9 bits (lanes 1-2) is X
wire signed [63:0] p0 = sx_ax * sx_ay;
wire signed [63:0] p1 = sx_bx * sx_by;
wire m9_negneg = (signed_max == "true") && (signed_may == "true") && e_ax[ax_width-1] && e_ay[ay_scan_in_width-1];
wire m9_wide = m9 && (ax_width > 9 || ay_scan_in_width > 9);
wire [63:0] comb = (!supported || m9_wide) ? {64{1'bx}} : s2 ? (p0 + p1) : m9 ? {{46{m9_negneg}}, p0[17:0]} : p0;

generate
    if (COUT >= 0) always @(posedge clk[COUT]) if (ena[COUT]) r_out <= comb;
endgenerate
wire [63:0] full = (COUT >= 0) ? r_out : comb;

assign resulta = full[result_a_width-1:0];
assign resultb = {result_b_width{1'bx}};
assign scanout = {scan_out_width{1'bx}};
assign chainout = {64{1'bx}};
assign dftout = 1'b0;
endmodule
