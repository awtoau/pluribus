module top(input clk, input ce0, input ac0, input we, input [8:0] aa, input [15:0] da, input [1:0] bea, output [15:0] qa);
  cycloneiv_ram_block #(
    .operation_mode("single_port"),
    .ram_block_type("M9K"),
    .logical_ram_name("ram"),
    .port_a_logical_ram_depth(512),
    .port_a_logical_ram_width(16),
    .port_a_first_address(0),
    .port_a_last_address(511),
    .port_a_first_bit_number(0),
    .port_a_data_width(16),
    .port_a_address_width(9),
    .power_up_uninitialized("false"),
    .port_a_byte_enable_mask_width(1),
    .clk0_core_clock_enable("none")
  ) ram (
    .clk0(clk), .ena0(ce0), .portaaddr(aa), .portadatain(da), .portadataout(qa), .portabyteenamasks(bea[0:0]), .portawe(we));
endmodule
