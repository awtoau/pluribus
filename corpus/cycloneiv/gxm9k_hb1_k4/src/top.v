module top(input clk, input we, input [12:0] addr, input [0:0] d, output [0:0] q);
  altsyncram #(
    .operation_mode("SINGLE_PORT"),
    .width_a(1),
    .widthad_a(13),
    .numwords_a(8192),
    .ram_block_type("M9K"),
    .init_file("../src/init.mif"),
    .outdata_reg_a("UNREGISTERED"),
    .lpm_type("altsyncram"),
    .power_up_uninitialized("FALSE")
  ) ram (
    .clock0(clk), .wren_a(we), .address_a(addr), .data_a(d), .q_a(q));
endmodule
