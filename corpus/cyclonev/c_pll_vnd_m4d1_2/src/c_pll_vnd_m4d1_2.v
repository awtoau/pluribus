module c_pll_vnd_m4d1_2 (input refclk, input rst, output [7:0] q, output locked);
  wire [1:0] oc;
  reg [3:0] c0;
  always @(posedge oc[0]) c0 <= c0 + 1;
  reg [3:0] c1;
  always @(posedge oc[1]) c1 <= c1 + 1;
  assign q = {c1, c0};
  altera_pll #(.fractional_vco_multiplier("false"), .reference_clock_frequency("50.0 MHz"), .operation_mode("direct"), .number_of_clocks(2), .output_clock_frequency0("200.0 MHz"), .phase_shift0("0 ps"), .duty_cycle0(50), .output_clock_frequency1("100.0 MHz"), .phase_shift1("0 ps"), .duty_cycle1(50), .pll_type("General"), .pll_subtype("General")) p (.rst(rst), .outclk(oc), .locked(locked), .refclk(refclk), .fboutclk(), .fbclk(1'b0));
endmodule
