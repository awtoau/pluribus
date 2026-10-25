// Own behavioural model of an enabled Cyclone V fractional PLL (FPLL tile), integer mode.
// The vendor atoms (cyclonev_fractional_pll, cyclonev_pll_output_counter) are encrypted; this model's
// behaviour was measured from them in Questa (scripts/cyclonev_lifted_sim_check.py --sim questa, issue #121):
// - lock: 1 at the first refclk posedge with reset inactive; 0 at once on reset (vendor sim model; real
//   silicon takes longer to lock).
// - VCO: refclk * M / N, first rising edge at lock, re-aligned to refclk every N/gcd(M,N) refclk cycles;
//   stops while unlocked.  Refclk period is measured (needs 2 refclk edges before lock).
// - output counter c: HI + LO VCO cycles, high for HI; ODD_DUTY: falls on the VCO negedge half a cycle
//   early.  Counter state is kept across reset; the first VCO edge after power-up is not counted.
// Not modelled (the lifter reports these as NOT LIFTED): fractional mode, phase shift / presets,
// counter cascade, clock switchover, dynamic reconfiguration.
`timescale 1ps/1ps
module pluribus_cv_fpll #(
    parameter integer M = 1,
    parameter integer N = 1,
    parameter integer NRESET_INVERT = 1,     // 1: nreset is active-high (Quartus nreset_invert = "true")
    parameter [9*8-1:0] C_HI = 0,            // per counter c (0..8): high VCO cycles, byte c
    parameter [9*8-1:0] C_LO = 0,            // per counter c: low VCO cycles
    parameter [8:0] C_ODD = 0,               // per counter c: odd-division even-duty correction
    parameter [8:0] C_EN = 0                 // per counter c: output enabled
) (
    input wire refclk,
    input wire nreset,
    output reg locked,
    output wire [8:0] clkout
);
    function integer gcd(input integer a, input integer b); integer t; begin
        while (b != 0) begin t = a % b; a = b; b = t; end
        gcd = a;
    end endfunction
    localparam integer G = gcd(M, N);
    localparam integer MR = M / G;            // VCO cycles per re-alignment window
    localparam integer NR = N / G;            // refclk cycles per window
    wire rst = NRESET_INVERT ? nreset : !nreset;

    initial locked = 0;
    always @(posedge refclk or posedge rst)
        if (rst) locked <= 0; else locked <= 1;

    real tlast, tref;
    reg have_last = 0, have_ref = 0;
    integer win = 0;
    reg vco = 0;
    event start;
    always @(posedge refclk) begin
        if (have_last) begin tref = $realtime - tlast; have_ref = 1; end
        tlast = $realtime; have_last = 1;
        if (!rst && have_ref) begin
            if (win == 0) -> start;
            win = (win + 1) % NR;
        end
    end
    always @(posedge rst) begin
        disable burst;
        vco = 0;
        win = 0;
    end
    always @(start) begin : burst
        integer k;
        real t0, tv;
        t0 = $realtime;
        tv = tref * NR / MR;
        for (k = 0; k < MR; k = k + 1) begin
            #(t0 + k * tv - $realtime) vco = 1;
            #(t0 + k * tv + tv / 2 - $realtime) vco = 0;
        end
    end

    reg armed = 0;
    always @(posedge vco) armed <= 1;
    genvar c;
    generate for (c = 0; c < 9; c = c + 1) begin : cnt
        localparam integer HI = C_HI[8*c +: 8];
        localparam integer LO = C_LO[8*c +: 8];
        localparam integer CN = HI + LO;
        integer pos = (HI + LO > 0) ? HI + LO - 1 : 0;
        reg out = 0;
        assign clkout[c] = C_EN[c] ? out : 1'b0;
        always @(posedge vco) if (armed && CN > 0) begin
            pos = (pos + 1) % CN;
            if (pos == 0) out = 1;
            else if (pos == HI && !(C_ODD[c] && HI > 1)) out = 0;
        end
        always @(negedge vco) if (C_ODD[c] && HI > 1 && pos == HI - 1) out = 0;
    end endgenerate
endmodule
