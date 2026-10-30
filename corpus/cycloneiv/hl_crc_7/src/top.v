module top (
  input clk,
  output y
);
reg [15:0] crc1;
function [15:0] crcf2(input [15:0] cc, input [7:0] x);
  integer i; reg [15:0] rr;
  begin
    rr = cc;
    for (i = 0; i < 8; i = i + 1) rr = (rr[15] ^ x[7 - i]) ? ((rr << 1) ^ 16'h8005) : (rr << 1);
    crcf2 = rr;
  end
endfunction
reg [31:0] stim0;
reg [15:0] crc3;
function [15:0] crcf4(input [15:0] cc, input [15:0] x);
  integer i; reg [15:0] rr;
  begin
    rr = cc;
    for (i = 0; i < 16; i = i + 1) rr = (rr[15] ^ x[15 - i]) ? ((rr << 1) ^ 16'h1021) : (rr << 1);
    crcf4 = rr;
  end
endfunction
reg y_q;
always @(posedge clk) stim0 <= {stim0[30:0], ~(stim0[31] ^ stim0[21] ^ stim0[1] ^ stim0[0])};
always @(posedge clk) if (stim0[24] & stim0[31] & stim0[7]) crc1 <= {16{1'b1}}; else if (stim0[0]) crc1 <= crcf2(crc1, {stim0[30], stim0[20], stim0[5], stim0[15], stim0[8], stim0[13], stim0[10], stim0[18]});
always @(posedge clk) if (stim0[28] & stim0[4] & stim0[2]) crc3 <= {16{1'b1}}; else if (stim0[14]) crc3 <= crcf4(crc3, {stim0[19], stim0[11], stim0[9], stim0[6], stim0[1], stim0[27], stim0[26], stim0[16], stim0[23], stim0[29], stim0[12], stim0[17], stim0[3], stim0[21], stim0[22], stim0[25]});
always @(posedge clk) y_q <= (^crc1) ^ (^crc3);
assign y = y_q;
endmodule
