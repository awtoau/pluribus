// syscfg_jtag_dis_done — Item 5 (#62): probe CIB_CFG2 uncatalogued sysConfig bit.
// Minimal design; all variation is in LPF SYSCONFIG preferences.
module fuzz (
    input  wire clk,
    input  wire d0,
    output wire out0
);
reg r;
always @(posedge clk) r <= d0;
assign out0 = r;
endmodule
