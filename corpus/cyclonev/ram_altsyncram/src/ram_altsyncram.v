// 512x16 single-port M10K, explicit altsyncram instance, output registered.
module ram_altsyncram(input clk, input we, input [8:0] addr, input [15:0] wdata,
                      output [15:0] rdata);
  altsyncram #(
    .operation_mode("SINGLE_PORT"),
    .width_a(16), .widthad_a(9), .numwords_a(512),
    .outdata_reg_a("CLOCK0"),
    .ram_block_type("M10K"),
    .intended_device_family("Cyclone V"),
    .lpm_type("altsyncram"),
    .power_up_uninitialized("FALSE"),
    .read_during_write_mode_port_a("NEW_DATA_NO_NBE_READ"),
    .width_byteena_a(1)
  ) u_ram (
    .clock0(clk), .address_a(addr), .data_a(wdata), .wren_a(we), .q_a(rdata),
    .aclr0(1'b0), .aclr1(1'b0), .address_b(1'b1), .addressstall_a(1'b0),
    .addressstall_b(1'b0), .byteena_a(1'b1), .byteena_b(1'b1), .clock1(1'b1),
    .clocken0(1'b1), .clocken1(1'b1), .clocken2(1'b1), .clocken3(1'b1),
    .data_b(1'b1), .eccstatus(), .q_b(), .rden_a(1'b1), .rden_b(1'b1),
    .wren_b(1'b0)
  );
endmodule
