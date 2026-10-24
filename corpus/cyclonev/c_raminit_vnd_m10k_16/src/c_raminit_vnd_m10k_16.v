module c_raminit_vnd_m10k_16 (clk, we, waddr, raddr, din, dout);
  input clk, we;
  input [5:0] waddr, raddr;
  input [15:0] din;
  output [15:0] dout;
  reg [15:0] dout;
  (* ramstyle = "M10K" *) reg [15:0] mem [0:63];
  integer i;
  initial for (i = 0; i < 64; i = i + 1) mem[i] = (i * 37 + 11) ^ (i >> 2) ^ (i * 21);
  always @(posedge clk) begin
    if (we) mem[waddr] <= din;
    dout <= mem[raddr];
  end
endmodule
