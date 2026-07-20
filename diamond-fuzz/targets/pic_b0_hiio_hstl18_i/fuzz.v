// pic_b0_hiio_hstl18_i — Gap 3 (#62): probe CIB_PIC_B0 frames F24-F27.
// clk/d0 on bank 0 (pin 88/87), outputs on bank 2 (bottom edge) with HSTL18_I.
module fuzz (
    input wire clk,
    input wire d0,
    output wire out0, out1, out2, out3
);
reg [3:0] r;
always @(posedge clk) r <= {{r[2:0], d0}};
assign {{out3, out2, out1, out0}} = r;
endmodule
