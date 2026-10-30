module top (
  input clk,
  output y
);
reg [31:0] crc1;
function [31:0] crcf2(input [31:0] cc, input [7:0] x);
  integer i; reg [31:0] rr;
  begin
    rr = cc;
    for (i = 0; i < 8; i = i + 1) rr = (rr[31] ^ x[7 - i]) ? ((rr << 1) ^ 32'h1EDC6F41) : (rr << 1);
    crcf2 = rr;
  end
endfunction
reg [31:0] stim0;
reg y_q;
always @(posedge clk) stim0 <= {stim0[30:0], ~(stim0[31] ^ stim0[21] ^ stim0[1] ^ stim0[0])};
always @(posedge clk) if (stim0[28] & stim0[21] & stim0[29]) crc1 <= {32{1'b1}}; else if (stim0[5]) crc1 <= crcf2(crc1, {stim0[8], stim0[20], stim0[7], stim0[22], stim0[27], stim0[14], stim0[19], stim0[12]});
always @(posedge clk) y_q <= (^crc1);
assign y = y_q;
endmodule
