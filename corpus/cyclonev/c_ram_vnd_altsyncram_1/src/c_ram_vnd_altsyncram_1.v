module c_ram_vnd_altsyncram_1 (clk, we, waddr, raddr, din, dout);
  input clk, we;
  input [5:0] waddr, raddr;
  input [0:0] din;
  output [0:0] dout;
  altsyncram #(.operation_mode("DUAL_PORT"), .width_a(1), .widthad_a(6), .numwords_a(64), .width_b(1), .widthad_b(6), .numwords_b(64), .outdata_reg_b("UNREGISTERED"), .address_reg_b("CLOCK0"), .ram_block_type("AUTO"), .intended_device_family("Cyclone V"), .lpm_type("altsyncram"), .power_up_uninitialized("FALSE")) u (.clock0(clk), .address_a(waddr), .data_a(din), .wren_a(we), .address_b(raddr), .q_b(dout));
endmodule
