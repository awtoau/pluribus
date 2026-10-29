module top(input clk, input we, input [8:0] addr, input [17:0] d, output [17:0] q);
  altsyncram #(
    .operation_mode("SINGLE_PORT"),
    .width_a(18),
    .widthad_a(9),
    .numwords_a(512),
    .ram_block_type("M9K"),
    .init_file("../src/init.mif"),
    .outdata_reg_a("UNREGISTERED"),
    .lpm_type("altsyncram"),
    .power_up_uninitialized("FALSE")
  ) ram (
    .clock0(clk), .wren_a(we), .address_a(addr), .data_a(d), .q_a(q));
endmodule
