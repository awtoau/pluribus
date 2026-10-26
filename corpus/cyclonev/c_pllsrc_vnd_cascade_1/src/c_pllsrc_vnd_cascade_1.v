module c_pllsrc_vnd_cascade_1 (input refclk, input rst, output [3:0] q, output locked);
  wire [0:0] oc, oc1;
  wire lk1;
  reg [3:0] c0;
  always @(posedge oc[0]) c0 <= c0 + 1;
  assign q = c0;
  altera_pll #(.fractional_vco_multiplier("false"), .reference_clock_frequency("50.0 MHz"), .operation_mode("direct"), .number_of_clocks(1), .output_clock_frequency0("100.0 MHz"), .phase_shift0("0 ps"), .duty_cycle0(50), .pll_type("General"), .pll_subtype("General")) p1 (.rst(rst), .outclk(oc1), .locked(lk1), .refclk(refclk), .fboutclk(), .fbclk(1'b0));
  altera_pll #(.fractional_vco_multiplier("false"), .reference_clock_frequency("100.0 MHz"), .operation_mode("direct"), .number_of_clocks(1), .output_clock_frequency0("200.0 MHz"), .phase_shift0("0 ps"), .duty_cycle0(50), .pll_type("General"), .pll_subtype("General")) p (.rst(rst), .outclk(oc), .locked(locked), .refclk(oc1[0]), .fboutclk(), .fbclk(1'b0));
endmodule
