module c_rom_vnd_m10k_8 (clk, addr, dout);
  input clk;
  input [6:0] addr;
  output [7:0] dout;
  reg [7:0] dout;
  (* ramstyle = "M10K" *) reg [7:0] mem [0:127];
  integer i;
  initial for (i = 0; i < 128; i = i + 1) mem[i] = (i * 37 + 11) ^ (i >> 2) ^ (i * 13);
  always @(posedge clk) dout <= mem[addr];
endmodule
