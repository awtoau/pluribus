module top (
  input clk,
  output y
);
reg [31:0] stim0;
reg [1:0] pe1;
reg pv2;
reg [2:0] pe3;
reg pv4;
reg y_q;
always @(posedge clk) stim0 <= {stim0[30:0], ~(stim0[31] ^ stim0[21] ^ stim0[1] ^ stim0[0])};
always @(posedge clk) begin
  pv2 <= |{stim0[6], stim0[2], stim0[16], stim0[12]};
  casez ({stim0[6], stim0[2], stim0[16], stim0[12]})
    4'b???1: pe1 <= 2'd0;
    4'b??10: pe1 <= 2'd1;
    4'b?100: pe1 <= 2'd2;
    4'b1000: pe1 <= 2'd3;
    default: pe1 <= 2'd0;
  endcase
end
always @(posedge clk) begin
  pv4 <= |{stim0[31], stim0[11], stim0[8], stim0[4], stim0[17], stim0[30], stim0[15], stim0[22]};
  casez ({stim0[31], stim0[11], stim0[8], stim0[4], stim0[17], stim0[30], stim0[15], stim0[22]})
    8'b???????1: pe3 <= 3'd0;
    8'b??????10: pe3 <= 3'd1;
    8'b?????100: pe3 <= 3'd2;
    8'b????1000: pe3 <= 3'd3;
    8'b???10000: pe3 <= 3'd4;
    8'b??100000: pe3 <= 3'd5;
    8'b?1000000: pe3 <= 3'd6;
    8'b10000000: pe3 <= 3'd7;
    default: pe3 <= 3'd0;
  endcase
end
always @(posedge clk) y_q <= (^pe1) ^ pv2 ^ (^pe3) ^ pv4;
assign y = y_q;
endmodule
