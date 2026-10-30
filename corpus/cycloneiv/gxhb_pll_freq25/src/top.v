module top(input clk, output [0:0] q, output l);
  wire [4:0] c;
  reg q0; always @(posedge c[0]) q0 <= ~q0;
  assign q = {q0};
  altpll #(
    .operation_mode("NORMAL"),
    .pll_type("AUTO"),
    .compensate_clock("CLK0"),
    .inclk0_input_frequency(40000),
    .clk0_multiply_by(2),
    .clk0_divide_by(1),
    .clk0_phase_shift("0"),
    .clk0_duty_cycle(50),
    .bandwidth_type("AUTO"),
    .intended_device_family("Cyclone IV GX"),
    .lpm_type("altpll")
  ) pll (
    .inclk({1'b0, clk}), .clk(c), .locked(l));
endmodule
