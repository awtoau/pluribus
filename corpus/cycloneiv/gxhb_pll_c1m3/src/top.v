module top(input clk, output [1:0] q, output l);
  wire [4:0] c;
  reg q0; always @(posedge c[0]) q0 <= ~q0; reg q1; always @(posedge c[1]) q1 <= ~q1;
  assign q = {q1, q0};
  altpll #(
    .operation_mode("NORMAL"),
    .pll_type("AUTO"),
    .compensate_clock("CLK0"),
    .inclk0_input_frequency(20000),
    .clk0_multiply_by(2),
    .clk0_divide_by(1),
    .clk0_phase_shift("0"),
    .clk0_duty_cycle(50),
    .bandwidth_type("AUTO"),
    .clk1_multiply_by(3),
    .clk1_divide_by(1),
    .intended_device_family("Cyclone IV GX"),
    .lpm_type("altpll")
  ) pll (
    .inclk({1'b0, clk}), .clk(c), .locked(l));
endmodule
