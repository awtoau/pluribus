module top(input clk, input clk1, input ce0, input ce1, input ac0, input wea, input web, input [8:0] aa, input [8:0] ab, input [15:0] da, input [15:0] db, input [0:0] bea, output [15:0] qa, output [15:0] qb);
  wire [15:0] qa_w; wire [15:0] qb_w;
  assign qa = qa_w; assign qb = 0;
  altsyncram #(
    .operation_mode("SINGLE_PORT"),
    .width_a(16),
    .widthad_a(9),
    .numwords_a(512),
    .width_b(16),
    .widthad_b(9),
    .numwords_b(512),
    .width_byteena_a(1),
    .ram_block_type("M9K"),
    .outdata_reg_a("CLOCK0"),
    .outdata_reg_b("UNREGISTERED"),
    .address_reg_b("CLOCK0"),
    .indata_aclr_a("NONE"),
    .wrcontrol_aclr_a("NONE"),
    .address_aclr_a("NONE"),
    .outdata_aclr_a("CLEAR0"),
    .byteena_aclr_a("NONE"),
    .address_aclr_b("NONE"),
    .outdata_aclr_b("NONE"),
    .clock_enable_input_a("NORMAL"),
    .clock_enable_output_a("NORMAL"),
    .clock_enable_input_b("NORMAL"),
    .clock_enable_output_b("NORMAL"),
    .read_during_write_mode_port_a("NEW_DATA_NO_NBE_READ"),
    .read_during_write_mode_mixed_ports("DONT_CARE"),
    .power_up_uninitialized("FALSE"),
    .byte_size(8),
    .lpm_type("altsyncram"),
    .init_file("../src/init.mif"),
    .indata_reg_b("CLOCK0"),
    .wrcontrol_wraddress_reg_b("CLOCK0"),
    .byteena_reg_b("CLOCK0")
  ) ram (
    .clock0(clk), .clocken0(ce0), .address_a(aa), .wren_a(wea), .data_a(da), .q_a(qa_w), .aclr0(ac0));
endmodule
