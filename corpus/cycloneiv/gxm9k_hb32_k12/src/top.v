module top(input clk, input we, input [7:0] addr, input [31:0] d, output [31:0] q);
  altsyncram #(
    .operation_mode("SINGLE_PORT"),
    .width_a(32),
    .widthad_a(8),
    .numwords_a(256),
    .ram_block_type("M9K"),
    .init_file("../src/init.mif"),
    .outdata_reg_a("UNREGISTERED"),
    .lpm_type("altsyncram"),
    .power_up_uninitialized("FALSE")
  ) ram (
    .clock0(clk), .wren_a(we), .address_a(addr), .data_a(d), .q_a(q));
endmodule
