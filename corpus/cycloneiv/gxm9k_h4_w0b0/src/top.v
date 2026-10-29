module top(input clk, input we, input [10:0] addr, input [3:0] d, output [3:0] q);
  altsyncram #(
    .operation_mode("SINGLE_PORT"),
    .width_a(4),
    .widthad_a(11),
    .numwords_a(2048),
    .ram_block_type("M9K"),
    .init_file("../src/init.mif"),
    .outdata_reg_a("UNREGISTERED"),
    .lpm_type("altsyncram"),
    .power_up_uninitialized("FALSE")
  ) ram (
    .clock0(clk), .wren_a(we), .address_a(addr), .data_a(d), .q_a(q));
endmodule
