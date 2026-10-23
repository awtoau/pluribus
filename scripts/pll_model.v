// Behavioural MachXO2 EHXPLLJ (INT_DIVD feedback), SIMULATION ONLY.
// Dividers come from the bitstream (pll_decode.py); Fvco = Fin * FB_DIV / I_DIV,
// Fout = Fvco / OUT_DIV.  Input period is measured from CLKI, so the model follows
// whatever reference the testbench drives.  Not modelled: phase (CPHASE words),
// lock time (LOCK rises at the first measured period), jitter, VCO range, WB port.
`timescale 1ns/1ps
module pll_model #(
    parameter integer I_DIV = 1, FB_DIV = 1,
    parameter integer OP_DIV = 1, OS_DIV = 1, OS2_DIV = 1, OS3_DIV = 1
) (
    input  wire CLKI,
    output reg  CLKOP = 1'b0, CLKOS = 1'b0, CLKOS2 = 1'b0, CLKOS3 = 1'b0,
    output reg  LOCK = 1'b0
);
    realtime t_prev = 0.0, t_in = 0.0;
    always @(posedge CLKI) begin
        if (t_prev != 0.0) begin t_in = $realtime - t_prev; LOCK <= 1'b1; end
        t_prev = $realtime;
    end
    // half period of an output = Tin * I_DIV / FB_DIV * OUT_DIV / 2
    function realtime half(input integer d);
        half = t_in * I_DIV * d / FB_DIV / 2.0;
    endfunction
    always @(posedge LOCK) begin : gen_op   forever begin #(half(OP_DIV))  CLKOP  = ~CLKOP;  end end
    always @(posedge LOCK) begin : gen_os   forever begin #(half(OS_DIV))  CLKOS  = ~CLKOS;  end end
    always @(posedge LOCK) begin : gen_os2  forever begin #(half(OS2_DIV)) CLKOS2 = ~CLKOS2; end end
    always @(posedge LOCK) begin : gen_os3  forever begin #(half(OS3_DIV)) CLKOS3 = ~CLKOS3; end end
endmodule
